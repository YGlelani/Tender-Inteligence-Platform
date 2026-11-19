export const state = {

    user: null,

    stats: null,

    feed: [],

    page: 1,

    pageSize: 10,

    query: "",

    total: 0,

    range: 90

};


export function setState(patch) {

    Object.assign(
        state,
        patch
    );

}